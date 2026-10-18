package main

func compute() int {
	return 1
}

func helper(x int) int {
	return x + 1
}

func main() {
	v := compute()
	helper(v)
}
