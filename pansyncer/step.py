"""
pansyncer step.py
Cycles through a list of tuning increments
"""
class StepController:
    """ Set the frequency steps, which device inputs will change. """
    STEPS = [10, 100, 1000, 10000]

    def __init__(self):
        self.steps = self.STEPS
        self.index = 1  # default = 100 Hz

    def next_step(self):
        self.index = (self.index + 1) % len(self.steps)

    def get_step(self):
        return self.steps[self.index]

    def set_step(self, step):
        if step in self.steps:
            self.index = self.steps.index(step)
