from carrera_control.training_runtime import forward_node_delta


def test_forward_node_delta_wraps_at_the_finish_line() -> None:
    assert forward_node_delta(98, 2, 100) == 4


def test_forward_node_delta_rejects_an_implausibly_large_jump() -> None:
    assert forward_node_delta(10, 80, 100) == 0