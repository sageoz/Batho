fn compute() -> i32 {
    1
}

fn helper(x: i32) -> i32 {
    x + 1
}

fn main() {
    let v = compute();
    let _ = helper(v);
}
