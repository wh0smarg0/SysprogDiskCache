class IORequest:
    """Запит на читання або запис одного сектора."""

    def __init__(self, process_id, sector_number, is_write=False):
        self.process_id = process_id
        self.sector_number = sector_number
        self.is_write = is_write


class IOScheduler:
    def __init__(self, algorithm="FIFO", sectors_per_track=500,
                 total_tracks=10000, seek_per_track=0.5,
                 edge_seek_time=10.0):
        self.algorithm = algorithm
        self.sectors_per_track = sectors_per_track
        self.total_tracks = total_tracks
        self.seek_per_track = seek_per_track
        self.edge_seek_time = edge_seek_time
        self.queue = []
        self.look_direction = 1
        self.max_contiguous = 3
        self.current_track_count = 0
        self.last_accessed_track = -1
        self.active_queue = []
        self.pending_queue = []
        self.flook_direction = 1

    def _track_of(self, request):
        return request.sector_number // self.sectors_per_track

    def _seek_time(self, start_track, target_track):
        """Мінімум прямого переходу і переходу через край диска."""
        direct = abs(target_track - start_track) * self.seek_per_track
        via_first = self.edge_seek_time + target_track * self.seek_per_track
        via_last = (self.edge_seek_time
                    + (self.total_tracks - 1 - target_track) * self.seek_per_track)
        return min(direct, via_first, via_last)

    def add_request(self, request):
        if self.algorithm in ("FIFO", "LOOK"):
            self.queue.append(request)
        elif self.algorithm == "FLOOK":
            self.pending_queue.append(request)
        else:
            raise ValueError(f"Невідомий алгоритм планування: {self.algorithm}")

    def get_next_request(self, current_track):
        if self.algorithm == "FIFO":
            return self.queue.pop(0) if self.queue else None
        if self.algorithm == "LOOK":
            return self._get_look(current_track)
        if self.algorithm == "FLOOK":
            return self._get_flook(current_track)
        raise ValueError(f"Невідомий алгоритм планування: {self.algorithm}")

    def _directional(self, requests, current_track, direction):
        if direction > 0:
            return [r for r in requests if self._track_of(r) >= current_track]
        return [r for r in requests if self._track_of(r) <= current_track]

    def _sorted(self, requests, direction):
        return sorted(requests, key=lambda r: r.sector_number,
                      reverse=(direction < 0))

    def _get_look(self, current_track):
        if not self.queue:
            return None

        candidates = self._directional(self.queue, current_track,
                                       self.look_direction)
        if not candidates:
            # Порівнюємо переходи до крайніх секторів черги.
            ordered = sorted(self.queue, key=lambda r: r.sector_number)
            extremes = [ordered[0], ordered[-1]]
            target = min(extremes, key=lambda r: self._seek_time(
                current_track, self._track_of(r)))
            target_track = self._track_of(target)
            self.look_direction = 1 if target_track >= current_track else -1
            candidates = self._directional(self.queue, current_track,
                                           self.look_direction)

        ordered = self._sorted(candidates, self.look_direction)
        # Обмежуємо серію на одній доріжці, якщо є альтернатива.
        if self.current_track_count >= self.max_contiguous:
            alternatives = [r for r in ordered
                            if self._track_of(r) != self.last_accessed_track]
            if alternatives:
                ordered = alternatives

        selected = ordered[0]
        track = self._track_of(selected)
        if track == self.last_accessed_track:
            self.current_track_count += 1
        else:
            self.last_accessed_track = track
            self.current_track_count = 1
        self.queue.remove(selected)
        return selected

    def _get_flook(self, current_track):
        if not self.active_queue:
            if not self.pending_queue:
                return None
            self.active_queue, self.pending_queue = (
                self.pending_queue, self.active_queue)

        # NLOOK: рух в одному напрямку в межах активної черги.
        candidates = self._directional(self.active_queue, current_track,
                                       self.flook_direction)
        if not candidates:
            candidates = self.active_queue

        selected = self._sorted(candidates, self.flook_direction)[0]
        self.active_queue.remove(selected)
        return selected
