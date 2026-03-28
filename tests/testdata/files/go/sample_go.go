package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// Simple function
func add(a, b int) int {
	return a + b
}

// Struct with methods
type Person struct {
	Name    string `json:"name"`
	Age     int    `json:"age"`
	Private string `json:"-"`
}

func (p Person) DisplayName() string {
	return fmt.Sprintf("Person: %s", p.Name)
}

func (p *Person) SetAge(age int) {
	p.Age = age
}

// Interface implementation
type Shape interface {
	Area() float64
	Perimeter() float64
}

type Rectangle struct {
	Width  float64
	Height float64
}

func (r Rectangle) Area() float64 {
	return r.Width * r.Height
}

func (r Rectangle) Perimeter() float64 {
	return 2 * (r.Width + r.Height)
}

// Goroutine and channel example
func worker(id int, jobs <-chan int, results chan<- int) {
	for j := range jobs {
		fmt.Printf("Worker %d processing job %d\n", id, j)
		results <- j * 2
	}
}

func main() {
	// Basic usage
	fmt.Println("Hello, World!")
	
	// Slice operations
	numbers := []int{1, 2, 3, 4, 5}
	doubled := make([]int, len(numbers))
	for i, n := range numbers {
		doubled[i] = n * 2
	}
	
	// Map operations
	personMap := make(map[string]Person)
	personMap["john"] = Person{Name: "John", Age: 30}
	
	// Error handling
	file, err := os.Open("test.txt")
	if err != nil {
		log.Printf("Error opening file: %v", err)
		return
	}
	defer file.Close()
	
	// JSON marshaling
	person := Person{Name: "Alice", Age: 25, Private: "secret"}
	data, err := json.Marshal(person)
	if err != nil {
		log.Printf("Error marshaling JSON: %v", err)
		return
	}
	fmt.Printf("JSON: %s\n", string(data))
	
	// HTTP client
	resp, err := http.Get("https://api.example.com/data")
	if err != nil {
		log.Printf("HTTP error: %v", err)
		return
	}
	defer resp.Body.Close()
	
	// File path operations
	path := filepath.Join("dir", "subdir", "file.txt")
	ext := filepath.Ext(path)
	dir := filepath.Dir(path)
	
	fmt.Printf("Path: %s, Ext: %s, Dir: %s\n", path, ext, dir)
	
	// String operations
	text := "Hello, World!"
	upper := strings.ToUpper(text)
	contains := strings.Contains(text, "World")
	
	fmt.Printf("Upper: %s, Contains World: %t\n", upper, contains)
}
