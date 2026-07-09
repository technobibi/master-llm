class TodoList:
    def __init__(self):
        self.tasks = []

    def add(self, text):
        self.tasks.append(text)

    def list_tasks(self):
        return list(self.tasks)
