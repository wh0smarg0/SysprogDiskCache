import csv
from core.process import Process
from core.kernel import Kernel
from hardware.hard_disk import HardDisk
from memory.buffer_cache import LFUCache
from scheduling.io_scheduler import IOScheduler, IORequest
from core.simulator import Simulator

summary_results = []
CACHE_BUFFERS = 10

def run_simulation(algorithm, processes, description, is_slow_cpu=False, look_limit=None, disk_rpm=None):
    disk = HardDisk()
    if disk_rpm is not None:
        if disk_rpm <= 0:
            raise ValueError("RPM має бути додатним")
        disk.rpm = disk_rpm
        time_per_revolution = 60000 / disk.rpm
        disk.rotation_latency = time_per_revolution / 2
        disk.sector_rw_time = time_per_revolution / disk.sectors_per_track

    cache = LFUCache(total_buffers=CACHE_BUFFERS)
    scheduler = IOScheduler(algorithm=algorithm)
    if look_limit is not None and algorithm == "LOOK":
        scheduler.max_contiguous = look_limit

    kernel = Kernel()
    if is_slow_cpu:
        kernel.interrupt_handler_time = 0.05
        for p in processes:
            p.syscall_time = 15.0
            p.compute_time = 10.0
            p.remaining_time = p.syscall_time if p.stage == "SYSCALL" else p.compute_time

    sim = Simulator(processes, disk, cache, scheduler, kernel)
    sim.run()
    assert all(p.state == "DONE" for p in processes), f"Не всі процеси завершилися: {description}"
    summary_results.append({
        "Сценарій": description,
        "Алгоритм": algorithm,
        "Час (мс)": round(sim.now, 3),
        "Hits": sim.stats["hits"],
        "Misses": sim.stats["misses"],
        "Coalesced": sim.stats["coalesced"],
        "Читань": sim.stats["reads"],
        "Записів": sim.stats["writes"],
    })
    return sim, cache


def run_all_scenarios():
    summary_results.clear()
    run_simulation("FIFO", [Process("yyy", [('r', 100)])], "1: Просте читання")
    run_simulation("FIFO", [Process("yyy", [('w', 100)])], "2: Модифікація сектора")
    run_simulation("FIFO", [Process("yyy", [('r', 100)]), Process("qqq", [('w', 1000)])], "3: Читання та запис")
    run_simulation("FIFO", [Process("yyy", [('r', 100)]), Process("qqq", [('r', 100)])], "4: Дедуплікація")

    # 10 різних секторів заповнюють кеш, 11-й провокує витіснення dirty 100.
    sim, _ = run_simulation("FIFO", [Process("yyy", [('w', 100)] + [('r', s) for s in range(200, 1100, 100)] + [('w', 1100)])], "5: Витіснення (Write-back)")
    assert sim.stats["writes"] >= 2, "Сценарій 5: очікувався Write-back та запис сектора 1100"

    run_simulation("LOOK", [Process("yyy", [('w', 100)]), Process("qqq", [('r', 100)])], "6: LOOK (Читання+Запис)", look_limit=1)
    run_simulation("LOOK", [Process("yyy", [('r', 100)]), Process("qqq", [('r', 110)]), Process("eee", [('r', 1500)])], "7: LOOK (ліміт 1)", look_limit=1)
    run_simulation("LOOK", [Process("yyy", [('r', 100)]), Process("qqq", [('r', 110)]), Process("eee", [('r', 1500)])], "8: LOOK (ліміт 2)", look_limit=2)

    proc_s9 = [
        Process("yyy", [('r', 1000), ('r', 1500), ('r', 100)]),
        Process("qqq", [('w', 150), ('r', 700), ('r', 1250)]),
        Process("eee", [('r', 3000), ('w', 1550), ('r', 2700)]),
        Process("nnn", [('w', 1100), ('r', 3100)]),
    ]
    run_simulation("FLOOK", proc_s9, "9: FLOOK (Повільний CPU)", is_slow_cpu=True)

    # 11 процесів одночасно запитують 11 різних секторів.
    sim, _ = run_simulation("FIFO", [Process(f"p{i}", [('r', i * 100)]) for i in range(1, 12)], "10: Переповнення кешу")
    assert sim.stats["misses"] >= 11, "Сценарій 10: очікувалися щонайменше 11 промахів"

    sim, _ = run_simulation("FIFO", [Process("yyy", [('r', 100), ('r', 100)])], "11: Повторне читання (Cache Hit)")
    assert sim.stats["hits"] >= 1

    # Часте використання сектора 100 перед появою 11-го сектора.
    lfu_ops = [('r', s) for s in range(100, 1100, 100)] + [('r', 100)] * 3 + [('r', 1100)] + [('r', 100)]
    sim, cache = run_simulation("FIFO", [Process("lfu", lfu_ops)], "12: Перевірка витіснення LFU")
    assert sim.stats["hits"] >= 4, "Сценарій 12: сектор 100 повинен залишитися в кеші"
    assert any(b.sector_number == 100 for seg in (cache.left_segment, cache.middle_segment, cache.right_segment) for b in seg)

    # 10 секторів заповнюють кеш; наступний викликає витіснення dirty-сектора.
    writer_ops = [('w', 100)] + [('r', s) for s in range(200, 1100, 100)] + [('r', 1100)]
    sim, _ = run_simulation("FIFO", [Process("writer", writer_ops), Process("reader", [('r', 100)])], "13: Конкурентний Write-back", disk_rpm=1500)
    assert sim.stats["writes"] >= 1, "Сценарій 13: очікувався запис dirty-сектора"


def test_write_wait():
    print("\n" + "=" * 70)
    print("14: Контрольований тест WRITE WAIT")
    print("=" * 70)

    disk = HardDisk()
    cache = LFUCache(total_buffers=CACHE_BUFFERS)
    scheduler = IOScheduler(algorithm="FIFO")
    kernel = Kernel()

    for sector in range(100, 1100, 100):
        buffer, hit, write_back = cache.access_sector(sector, sector / 1000.0)
        assert buffer is not None and not hit and write_back is None

    dirty_buffer = next(b for b in cache.right_segment if b.sector_number == 100)
    dirty_buffer.is_dirty = True

    requester = Process("requester", [('r', 1100)])
    reader = Process("reader", [('r', 100)])
    sim = Simulator([requester], disk, cache, scheduler, kernel)
    requester.stage = "LOOKUP"
    requester.remaining_time = 0.0
    sim.current_process = requester
    requester.state = "RUNNING"
    requester.remaining_quantum = requester.quantum

    buffer, hit, write_back_sector = cache.access_sector(1100, sim.now)
    assert buffer is None and write_back_sector == 100
    sim.pending_buffer_retries.add(100)
    scheduler.add_request(IORequest("requester", 100, is_write=True))
    sim.dispatch_disk()

    sim.processes.append(reader)
    sim.ready_queue.append(reader)
    requester.state = "BLOCKED"
    requester.blocked_for_sector = None
    sim.waiting_for_buffer.append(requester)
    sim.current_process = None
    sim.run()

    assert requester.state == "DONE" and reader.state == "DONE"
    assert not sim.waiting_for_write and not sim.waiting_for_buffer
    assert not cache.has_dirty_buffers()
    print("\nTEST PASSED: WRITE WAIT")


def print_and_export_summary():
    if not summary_results:
        return
    keys = summary_results[0].keys()
    with open('summary.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(summary_results)

    print("\n" + "=" * 105)
    print(f"{'Сценарій':<38} | {'Алгоритм':<8} | {'Час (мс)':<10} | {'Hit':<4} | {'Miss':<4} | {'Coal':<4} | {'Read':<4} | {'Write':<4}")
    print("-" * 105)
    for r in summary_results:
        print(f"{r['Сценарій']:<38} | {r['Алгоритм']:<8} | {r['Час (мс)']:<10} | {r['Hits']:<4} | {r['Misses']:<4} | {r['Coalesced']:<4} | {r['Читань']:<4} | {r['Записів']:<4}")
    print("=" * 105)
    print("Таблицю збережено у файл 'summary.csv'.")


if __name__ == "__main__":
    run_all_scenarios()
    print_and_export_summary()
    test_write_wait()
