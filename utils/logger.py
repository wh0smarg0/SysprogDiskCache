class Logger:
    @staticmethod
    def log_event(time, process_id, event_type, details):
        """
        Форматує та виводить інформацію про дії в системі
        :param time: Поточний час симуляції
        :param process_id: ID процесу користувача
        :param event_type: Тип події (CACHE, DISK, SCHEDULER, PROCESS)
        :param details: Детальний опис
        """
        print(f"[{time:08.2f} мс] | Процес {process_id:2} | {event_type:<10} | {details}")

    @staticmethod
    def log_system(time, message):
        """Логування системних подій (наприклад, перемикання процесів)"""
        print(f"[{time:08.2f} мс] | СИСТЕМА    | {'-'*10} | {message}")