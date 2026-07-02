"""隠し評価テスト。エージェントには渡さず、実行後に runner.verify() が回す。"""
from fizzbuzz import fizzbuzz


def test_basic():
    assert fizzbuzz(5) == ["1", "2", "Fizz", "4", "Buzz"]


def test_fizz_buzz_fizzbuzz():
    out = fizzbuzz(15)
    assert out[2] == "Fizz"      # 3
    assert out[4] == "Buzz"      # 5
    assert out[14] == "FizzBuzz"  # 15


def test_length_and_type():
    out = fizzbuzz(100)
    assert len(out) == 100
    assert all(isinstance(x, str) for x in out)
