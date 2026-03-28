📁 (root)/
  📄 README.md
    - document (document) [L1-3]
    - header_1_Simple Python (element) [L1-1]
📁 src/ (Source Code)
  📄 calculator.py
    - add(a: int, b: int) -> int (function) [L4-6]
    - subtract(a: int, b: int) -> int (function) [L9-11]
    - multiply(a: int, b: int) -> int (function) [L14-16]
    - divide(a: float, b: float) -> float (function) [L19-23]
    - Calculator (class) [L26-43]
    - __init__(self) -> float (method) [L29-30]
    - calculate(self, op: str, a: float, b: float) -> float (method) [L32-39]
    - last_result(self) -> float | None (method) [L41-43]
  📄 utils.py
    - double(x: int) -> int (function) [L6-8]
    - create_calculator() -> Calculator (function) [L11-13]
📁 tests/ (Testing Suite)
  📄 test_calculator.py
    - test_add() (function) [L6-7]
    - test_subtract() (function) [L10-11]
    - test_calculator_history() (function) [L14-17]