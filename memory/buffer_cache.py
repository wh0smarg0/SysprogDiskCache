class Buffer:
    def __init__(self):
        self.sector_number = None
        self.counter = 0
        self.last_accessed = 0.0
        self.is_dirty = False
        self.pins = 0
        self.is_writing = False


class LFUCache:
    def __init__(self, total_buffers=10):
        self.total_buffers = total_buffers
        self.max_left = 3
        self.max_middle = 3

        if total_buffers <= self.max_left + self.max_middle:
            raise ValueError(
                "Кількість буферів повинна перевищувати "
                "суму лімітів лівого та середнього сегментів"
            )

        self.left_segment = []
        self.middle_segment = []
        self.right_segment = []
        self.free_buffers = [Buffer() for _ in range(total_buffers)]

    def _balance_segments(self):
        while len(self.left_segment) > self.max_left:
            self.middle_segment.insert(0, self.left_segment.pop())

        while len(self.middle_segment) > self.max_middle:
            self.right_segment.insert(0, self.middle_segment.pop())

    def _evict_buffer(self):
        unpinned_buffers = [
            buf for buf in self.right_segment
            if buf.pins == 0 and not buf.is_writing
        ]

        if not unpinned_buffers:
            return None

        min_counter = min(
            buf.counter for buf in unpinned_buffers
        )

        candidates = [
            buf for buf in unpinned_buffers
            if buf.counter == min_counter
        ]

        evicted_buffer = min(
            candidates,
            key=lambda b: b.last_accessed
        )

        if evicted_buffer.is_dirty:
            evicted_buffer.is_writing = True
            return evicted_buffer

        self.right_segment.remove(evicted_buffer)
        return evicted_buffer

    def access_sector(self, sector_number, current_time, is_write=False):
        buffer_to_write_back = None
        target_buffer = None
        source_segment = None

        for segment, name in [(self.left_segment, 'left'),
                              (self.middle_segment, 'middle'),
                              (self.right_segment, 'right')]:
            for buf in segment:
                if buf.sector_number == sector_number:
                    target_buffer = buf
                    source_segment = segment
                    name_of_source = name
                    break
            if target_buffer:
                break

        if target_buffer:
            source_segment.remove(target_buffer)
            if name_of_source in ['middle', 'right']:
                target_buffer.counter += 1

            self.left_segment.insert(0, target_buffer)
            target_buffer.last_accessed = current_time
            if is_write:
                target_buffer.is_dirty = True

            self._balance_segments()
            return target_buffer, True, None

        if self.free_buffers:
            new_buffer = self.free_buffers.pop(0)
        else:
            new_buffer = self._evict_buffer()

            if new_buffer is None:
                return None, False, None

            if new_buffer.is_dirty:
                return None, False, new_buffer.sector_number

        new_buffer.sector_number = sector_number
        new_buffer.counter = 1
        new_buffer.last_accessed = current_time
        new_buffer.is_dirty = False
        new_buffer.is_writing = False
        new_buffer.pins = 0

        self.left_segment.insert(0, new_buffer)
        self._balance_segments()

        return new_buffer, False, buffer_to_write_back

    def get_all_dirty_buffers(self):
        dirty_sectors = []
        for segment in [self.left_segment, self.middle_segment, self.right_segment]:
            for buf in segment:
                if buf.is_dirty and not buf.is_writing:
                    dirty_sectors.append(buf.sector_number)
                    buf.is_writing = True  # Захищаємо під час фінального скидання
        return dirty_sectors

    def has_dirty_buffers(self):
        return any(
            buf.is_dirty
            for segment in [
                self.left_segment,
                self.middle_segment,
                self.right_segment
            ]
            for buf in segment
        )