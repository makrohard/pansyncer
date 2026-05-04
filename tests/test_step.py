from pansyncer.step import StepController


def test_default_step_is_100_hz():
    step = StepController()
    assert step.get_step() == 100


def test_next_step_cycles_forward():
    step = StepController()

    assert step.get_step() == 100
    step.next_step()
    assert step.get_step() == 1000
    step.next_step()
    assert step.get_step() == 10000
    step.next_step()
    assert step.get_step() == 10
    step.next_step()
    assert step.get_step() == 100


def test_set_step_accepts_known_step():
    step = StepController()

    step.set_step(1000)

    assert step.get_step() == 1000


def test_set_step_ignores_unknown_step():
    step = StepController()

    step.set_step(12345)

    assert step.get_step() == 100