from scheduling.io_scheduler import IORequest
from utils.logger import Logger


class Simulator:
    def __init__(self, processes, disk, cache, scheduler, kernel):
        self.processes = processes
        self.disk = disk
        self.cache = cache
        self.scheduler = scheduler
        self.kernel = kernel

        self.ready_queue = [
            p for p in self.processes if p.state != "DONE"
        ]
        self.current_process = None

        self.now = 0.0
        self.disk_due = float("inf")
        self.active_io = None

        # Процеси, що очікують завантаження секторів
        self.pending_reads = {}

        # Процеси, що очікують вільного буфера
        self.waiting_for_buffer = []
        self.waiting_for_write = {}

        # Сектори, для яких уже заплановано Write-back
        self.pending_buffer_retries = set()

        self.flushing = False

        self.stats = {
            "hits": 0,
            "misses": 0,
            "coalesced": 0,
            "reads": 0,
            "writes": 0
        }

    def has_io_requests(self):
        if self.scheduler.algorithm == "FLOOK":
            return (
                len(self.scheduler.active_queue) > 0
                or len(self.scheduler.pending_queue) > 0
            )

        return len(self.scheduler.queue) > 0

    def get_cache_buffers(self):
        return (
            self.cache.left_segment
            + self.cache.middle_segment
            + self.cache.right_segment
        )

    def find_buffer(self, sector_number):
        for buffer in self.get_cache_buffers():
            if buffer.sector_number == sector_number:
                return buffer
        return None

    def make_ready(self, process):
        if process.state == "DONE":
            return

        if process is self.current_process:
            return

        if process not in self.ready_queue:
            process.state = "READY"
            self.ready_queue.append(process)

    def wake_buffer_waiters(self):
        if not self.waiting_for_buffer:
            return

        # Якщо всі буфери зайняті читанням або записом,
        # процеси залишаються заблокованими.
        available = bool(self.cache.free_buffers)

        if not available:
            available = any(
                b.pins == 0 and not b.is_writing
                for b in self.cache.right_segment
            )

        if not available:
            return

        process = self.waiting_for_buffer.pop(0)

        self.make_ready(process)

        Logger.log_event(
            self.now,
            process.process_id,
            "BUFFER READY",
            "Повторна спроба отримати буфер кешу."
        )

    def run(self):
        Logger.log_system(
            self.now,
            f"Запуск симуляції. Алгоритм: {self.scheduler.algorithm}"
        )

        while True:
            # 1. Переривання від диска
            if self.active_io and self.now >= self.disk_due:
                self.handle_interrupt()
                continue

            # 2. Перевірка завершення процесів
            all_done = all(
                p.is_completed()
                if hasattr(p, "is_completed")
                else p.state == "DONE"
                for p in self.processes
            )

            if all_done:
                if not self.has_io_requests() and self.active_io is None:
                    dirty_sectors = self.cache.get_all_dirty_buffers()

                    if dirty_sectors:
                        if not self.flushing:
                            self.flushing = True
                            Logger.log_system(
                                self.now,
                                "FLUSH BEGIN: Скидання змінених буферів на диск."
                            )

                        for sector in dirty_sectors:
                            self.scheduler.add_request(
                                IORequest(
                                    "SYS",
                                    sector,
                                    is_write=True
                                )
                            )

                        self.dispatch_disk()
                        continue

                    if (
                        not self.cache.has_dirty_buffers()
                        and not self.pending_reads
                        and not self.waiting_for_buffer
                        and not self.pending_buffer_retries
                        and not self.has_io_requests()
                        and self.active_io is None
                        and not self.waiting_for_write
                    ):
                        break

            # 3. Планування процесора
            if self.current_process is None:
                if self.ready_queue:
                    self.current_process = self.ready_queue.pop(0)

                    p = self.current_process
                    p.state = "RUNNING"
                    p.remaining_quantum = p.quantum

                    Logger.log_system(
                        self.now,
                        f"Процес {p.process_id} отримав процесор."
                    )

                else:
                    self.wake_buffer_waiters()

                    if self.ready_queue:
                        continue

                    if self.active_io is not None:
                        idle_time = max(
                            0.0,
                            self.disk_due - self.now
                        )

                        if idle_time > 0:
                            Logger.log_system(
                                self.now,
                                f"Процесор простоює {idle_time:.3f} мс..."
                            )

                        self.now = self.disk_due
                        continue

                    if self.has_io_requests():
                        self.dispatch_disk()

                        if self.active_io is not None:
                            continue

                        raise RuntimeError(
                            "Є запити I/O, але не вдалося "
                            "запустити операцію."
                        )

                    if self.pending_reads:
                        raise RuntimeError(
                            "Deadlock: процеси очікують читання, "
                            "але немає активних дискових операцій."
                        )

                    if self.waiting_for_buffer:
                        raise RuntimeError(
                            "Deadlock: процеси очікують буфер, "
                            "але жоден буфер не може бути звільнений."
                        )

                    if self.waiting_for_write:
                        raise RuntimeError(
                            "Deadlock: процеси очікують завершення "
                            "Write-back, але немає активних "
                            "дискових операцій."
                        )

                    if all_done:
                        raise RuntimeError(
                            "Усі процеси завершені, але фінальний "
                            "Flush не завершився."
                        )

                    raise RuntimeError(
                        "Deadlock: немає готових процесів "
                        "та активного I/O, але не всі "
                        "процеси завершені."
                    )

            p = self.current_process

            # 4. Перевірка кванта процесора
            if (
                p.remaining_quantum <= 0
                #and p.stage != "LOOKUP"
            ):
                Logger.log_system(
                    self.now,
                    f"Квант процесу {p.process_id} вичерпано."
                )

                p.state = "READY"
                self.make_ready_after_preemption(p)
                self.current_process = None
                continue

            # 5. Звернення до кешу
            if p.stage == "LOOKUP":
                op_type, sector = p.get_current_op()

                existing_buffer = self.find_buffer(sector)

                if existing_buffer is not None and existing_buffer.is_writing:
                    Logger.log_event(
                        self.now,
                        p.process_id,
                        "WRITE WAIT",
                        f"Очікування завершення запису сектора {sector}."
                    )

                    p.state = "BLOCKED"
                    p.blocked_for_sector = sector

                    self.waiting_for_write.setdefault(sector, []).append(p)

                    self.current_process = None
                    continue

                # Інший процес уже завантажує сектор
                if sector in self.pending_reads:
                    self.stats["coalesced"] += 1

                    Logger.log_event(
                        self.now,
                        p.process_id,
                        "COALESCE",
                        f"Приєднання до існуючого "
                        f"завантаження сектора {sector}."
                    )

                    if p not in self.pending_reads[sector]:
                        self.pending_reads[sector].append(p)

                        buffer = self.find_buffer(sector)
                        if buffer is not None:
                            buffer.pins += 1

                    p.state = "BLOCKED"
                    p.blocked_for_sector = sector
                    self.current_process = None
                    continue

                buffer, is_hit, write_back_sector = (
                    self.cache.access_sector(
                        sector,
                        self.now,
                        is_write=(op_type == "w")
                    )
                )

                # Немає вільного буфера
                if buffer is None:
                    if write_back_sector is not None:
                        # Потрібно спочатку записати dirty-буфер
                        if (
                            write_back_sector
                            not in self.pending_buffer_retries
                        ):
                            self.pending_buffer_retries.add(
                                write_back_sector
                            )

                            Logger.log_event(
                                self.now,
                                p.process_id,
                                "WRITE BACK",
                                "Очікування звільнення "
                                f"брудного сектора {write_back_sector}."
                            )

                            self.scheduler.add_request(
                                IORequest(
                                    p.process_id,
                                    write_back_sector,
                                    is_write=True
                                )
                            )

                        self.dispatch_disk()

                    else:
                        Logger.log_event(
                            self.now,
                            p.process_id,
                            "BUFFER WAIT",
                            f"Немає доступного буфера "
                            f"для сектора {sector}."
                        )

                    p.state = "BLOCKED"
                    p.blocked_for_sector = None

                    if p not in self.waiting_for_buffer:
                        self.waiting_for_buffer.append(p)

                    self.current_process = None
                    continue

                # CACHE HIT
                if is_hit:
                    self.stats["hits"] += 1

                    Logger.log_event(
                        self.now,
                        p.process_id,
                        "CACHE HIT",
                        f"Сектор {sector} знайдено в кеші."
                    )

                    if op_type == "w":
                        Logger.log_event(
                            self.now,
                            p.process_id,
                            "WRITE",
                            f"Буфер сектора {sector} "
                            "змінено (dirty)."
                        )

                        p.advance_op()

                        if p.state == "DONE":
                            self.current_process = None

                    else:
                        p.stage = "AFTER_READ"
                        p.remaining_time = p.compute_time

                    continue

                # CACHE MISS
                self.stats["misses"] += 1

                Logger.log_event(
                    self.now,
                    p.process_id,
                    "CACHE MISS",
                    f"Сектора {sector} немає в кеші."
                )

                self.pending_reads[sector] = [p]

                if write_back_sector is not None:
                    if (
                        write_back_sector
                        not in self.pending_buffer_retries
                    ):
                        self.pending_buffer_retries.add(
                            write_back_sector
                        )

                        self.scheduler.add_request(
                            IORequest(
                                p.process_id,
                                write_back_sector,
                                is_write=True
                            )
                        )

                self.scheduler.add_request(
                    IORequest(
                        p.process_id,
                        sector,
                        is_write=False
                    )
                )

                buffer.pins += 1

                self.dispatch_disk()

                p.state = "BLOCKED"
                p.blocked_for_sector = sector
                self.current_process = None
                continue

            # 6. Просування часу
            dt = min(
                p.remaining_time,
                p.remaining_quantum
            )

            if self.active_io is not None:
                dt = min(
                    dt,
                    max(0.0, self.disk_due - self.now)
                )

            if dt > 0:
                self.now += dt
                p.remaining_time -= dt
                p.remaining_quantum -= dt

                if p.stage == "SYSCALL":
                    self.kernel.system_time += dt

            if p.remaining_time <= 0:
                if p.stage == "BEFORE_WRITE":
                    p.stage = "SYSCALL"
                    p.remaining_time = p.syscall_time

                elif p.stage == "SYSCALL":
                    p.stage = "LOOKUP"

                elif p.stage == "AFTER_READ":
                    p.advance_op()

                    if p.state == "DONE":
                        self.current_process = None

    def make_ready_after_preemption(self, process):
        if process not in self.ready_queue:
            self.ready_queue.append(process)

    def dispatch_disk(self):
        if (
            self.active_io is None
            and self.has_io_requests()
        ):
            self.active_io = (
                self.scheduler.get_next_request(
                    self.disk.current_track
                )
            )

            if self.active_io is not None:
                if self.active_io.is_write:
                    self.stats["writes"] += 1
                else:
                    self.stats["reads"] += 1

                hw_time, _ = self.disk.process_request(
                    self.active_io.sector_number
                )

                self.disk_due = self.now + hw_time

                Logger.log_event(
                    self.now,
                    self.active_io.process_id,
                    "DISK START",
                    "Початок читання/запису сектора "
                    f"{self.active_io.sector_number}. "
                    f"Завершення о {self.disk_due:.3f} мс"
                )

    def handle_interrupt(self):
        req = self.active_io

        interrupted_process = self.current_process

        remaining_before_irq = (
            interrupted_process.remaining_time
            if interrupted_process is not None
            else None
        )

        if interrupted_process is not None:
            Logger.log_event(
                self.now,
                interrupted_process.process_id,
                "CPU INTERRUPTED",
                f"IRQ перервав стадію {interrupted_process.stage}. "
                f"Залишок виконання: "
                f"{interrupted_process.remaining_time:.3f} мс. "
                f"Залишок кванта: "
                f"{interrupted_process.remaining_quantum:.3f} мс."
            )

        Logger.log_event(
            self.now,
            "SYS",
            "IRQ BEGIN",
            "Переривання від диска "
            f"(сектор {req.sector_number})."
        )

        irq_time = self.kernel.interrupt_handler_time

        self.now += irq_time
        self.kernel.system_time += irq_time

        if interrupted_process is not None:
            assert abs(
                interrupted_process.remaining_time - remaining_before_irq
            ) < 1e-9, (
                "Помилка: IRQ змінив залишок виконання процесу."
            )

        if self.current_process is not None:
            self.current_process.remaining_quantum -= irq_time

        self.active_io = None

        # 1. Завершення запису на диск
        if req.is_write:
            buffer = self.find_buffer(
                req.sector_number
            )

            if buffer is not None and buffer.is_writing:
                buffer.is_writing = False
                buffer.is_dirty = False

            self.pending_buffer_retries.discard(
                req.sector_number
            )

            waiting = self.waiting_for_write.pop(
                req.sector_number, []
            )

            for process in waiting:
                process.blocked_for_sector = None
                self.make_ready(process)

                Logger.log_event(
                    self.now,
                    process.process_id,
                    "WRITE READY",
                    f"Запис сектора {req.sector_number} завершено."
                )

            Logger.log_event(
                self.now,
                "SYS",
                "WRITE COMMIT",
                f"Сектор {req.sector_number} "
                "успішно записано на диск."
            )

        # 2. Завершення читання з диска
        elif req.sector_number in self.pending_reads:
            waitlist = self.pending_reads.pop(
                req.sector_number
            )

            buffer = self.find_buffer(
                req.sector_number
            )

            if buffer is None:
                raise RuntimeError(
                    "Помилка кешу: сектор "
                    f"{req.sector_number} відсутній "
                    "після завершення читання."
                )

            buffer.pins = max(
                0,
                buffer.pins - len(waitlist)
            )

            for p in waitlist:
                op_type, _ = p.get_current_op()

                if op_type == "r":
                    p.stage = "AFTER_READ"
                    p.remaining_time = p.compute_time

                else:
                    buffer.is_dirty = True
                    buffer.last_accessed = self.now

                    Logger.log_event(
                        self.now,
                        p.process_id,
                        "WRITE",
                        f"Буфер сектора {req.sector_number} "
                        "змінено (dirty)."
                    )

                    p.advance_op()

                self.make_ready(p)

                Logger.log_event(
                    self.now,
                    p.process_id,
                    "WAKE UP",
                    f"Сектор {req.sector_number} завантажено."
                )

        Logger.log_event(
            self.now,
            "SYS",
            "IRQ END",
            "Завершення переривання."
        )

        self.wake_buffer_waiters()

        if interrupted_process is not None:
            Logger.log_event(
                self.now,
                interrupted_process.process_id,
                "CPU RESUME",
                f"Після IRQ: стадія {interrupted_process.stage}. "
                f"Залишок виконання: "
                f"{interrupted_process.remaining_time:.3f} мс. "
                f"Залишок кванта: "
                f"{interrupted_process.remaining_quantum:.3f} мс."
            )

        self.dispatch_disk()
