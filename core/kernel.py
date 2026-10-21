class Kernel:
    def __init__(self):
        # Константи часу для системних викликів та переривань
        self.syscall_read_time = 0.15
        self.syscall_write_time = 0.15
        self.interrupt_handler_time = 0.05

        self.system_time = 0.0

    def execute_syscall(self, is_write, current_process):
        """
        Виконує системний виклик до пошуку буфера в кеші.
        Час виклику ядро забирає від кванта часу процесу.
        """
        time_spent = self.syscall_write_time if is_write else self.syscall_read_time
        self.system_time += time_spent
        current_process.remaining_quantum -= time_spent
        return time_spent

    def handle_interrupt(self, current_process):
        """
        Опрацьовує переривання від контролера після читання/запису.
        Час обробника ядро забирає від кванта часу процесу.
        """
        self.system_time += self.interrupt_handler_time
        if current_process:
            current_process.remaining_quantum -= self.interrupt_handler_time
        return self.interrupt_handler_time