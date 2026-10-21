class HardDisk:
    def __init__(self, rpm=7500):
        if rpm <= 0:
            raise ValueError("RPM має бути додатним")
        self.total_tracks = 10000
        self.sectors_per_track = 500
        self.rpm = rpm

        # Характеристики жорсткого диска
        self.total_tracks = 10000
        self.sectors_per_track = 500
        self.rpm = 7500

        self.track_seek_time = 0.5  # мс на переміщення на 1 доріжку
        self.max_seek_time = 10.0  # мс до зовнішньої або першої доріжки

        # Обчислення затримок
        time_per_revolution = (60 * 1000) / self.rpm
        self.rotation_latency = time_per_revolution / 2.0  # Середня затримка обертання
        self.sector_rw_time = time_per_revolution / self.sectors_per_track  # Час читання/запису 1 сектора

        self.current_track = 0

    def calculate_seek_time(self, target_track):
        """Обчислює найшвидший час переходу на цільову доріжку"""
        if target_track == self.current_track:
            return 0.0

        # Варіант 1: Пряме переміщення механізму приводу
        distance = abs(target_track - self.current_track)
        direct_time = distance * self.track_seek_time  #

        # Варіант 2: Переміщення через першу (0) доріжку або кінцеву (10000-1)
        # Час = 10 мс + переміщення від краю до цільової доріжки
        time_via_first = self.max_seek_time + (target_track * self.track_seek_time)
        time_via_last = self.max_seek_time + ((self.total_tracks - 1 - target_track) * self.track_seek_time)

        # Диск обирає найшвидший можливий перехід
        return min(direct_time, time_via_first, time_via_last)

    def process_request(self, sector_number):
        """Імітує обробку сектора контролером і повертає витрачений час"""
        if not 0 <= sector_number < self.total_tracks * self.sectors_per_track:
            raise ValueError(f"Некоректний номер сектора: {sector_number}")
        # Визначаємо номер доріжки за номером сектора
        target_track = sector_number // self.sectors_per_track

        seek_time = self.calculate_seek_time(target_track)
        # Час позиціювання складається з часу пошуку та затримки обертання
        total_hardware_time = seek_time + self.rotation_latency + self.sector_rw_time

        self.current_track = target_track
        return total_hardware_time, target_track