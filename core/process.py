import random

class Process:
    def __init__(self, process_id, operations):
        self.process_id = process_id
        self.operations = operations  # Список операцій
        self.current_op_index = 0

        self.quantum = 20.0  # 20 мс
        self.remaining_quantum = 0.0

        # Константи часу (в мілісекундах)
        self.syscall_time = 0.15
        self.compute_time = 7.0

        self.state = "READY"
        self.stage = "SYSCALL" if self.operations[0][0] == 'r' else "BEFORE_WRITE"
        self.remaining_time = self.syscall_time if self.stage == "SYSCALL" else self.compute_time

        self.blocked_for_sector = None

    def get_current_op(self):
        if self.current_op_index < len(self.operations):
            return self.operations[self.current_op_index]
        return None

    def advance_op(self):
        self.current_op_index += 1
        op = self.get_current_op()
        if op:
            self.stage = "BEFORE_WRITE" if op[0] == 'w' else "SYSCALL"
            self.remaining_time = self.compute_time if self.stage == "BEFORE_WRITE" else self.syscall_time
        else:
            self.stage = "DONE"
            self.state = "DONE"