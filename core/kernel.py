class Kernel:
    def __init__(self):
        # Тривалість системних викликів та обробки переривань
        self.syscall_read_time = 0.15
        self.syscall_write_time = 0.15
        self.interrupt_handler_time = 0.05

        # Сумарний час роботи ядра
        self.system_time = 0.0

    def execute_syscall(self, is_write, current_process=None):
        """
        Повертає тривалість системного виклику.

        Фактичне виконання системного виклику моделюється
        у Simulator, де враховуються можливі переривання
        від дискового контролера.

        Метод не змінює модельний час і квант процесу.
        """
        return (
            self.syscall_write_time
            if is_write
            else self.syscall_read_time
        )

    def handle_interrupt(self, current_process=None):
        """
        Повертає тривалість обробки апаратного переривання.

        Просування модельного часу та списання кванта
        виконує Simulator.
        """
        return self.interrupt_handler_time