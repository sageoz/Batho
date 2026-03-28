// Sample Rust code for testing language detection

use std::collections::HashMap;
use std::fs::File;
use std::io::{self, Read};
use std::path::Path;

// Simple function
fn add(a: i32, b: i32) -> i32 {
    a + b
}

// Struct with methods
#[derive(Debug, Clone)]
struct Person {
    name: String,
    age: u32,
    private_data: String,
}

impl Person {
    fn new(name: String, age: u32) -> Self {
        Self {
            name,
            age,
            private_data: String::from("private"),
        }
    }
    
    fn display_name(&self) -> String {
        format!("Person: {}", self.name)
    }
    
    fn set_age(&mut self, age: u32) {
        self.age = age;
    }
}

// Trait implementation
trait Shape {
    fn area(&self) -> f64;
    fn perimeter(&self) -> f64;
}

#[derive(Debug)]
struct Rectangle {
    width: f64,
    height: f64,
}

impl Shape for Rectangle {
    fn area(&self) -> f64 {
        self.width * self.height
    }
    
    fn perimeter(&self) -> f64 {
        2.0 * (self.width + self.height)
    }
}

// Enums and pattern matching
#[derive(Debug)]
enum Status {
    Connected,
    Disconnected,
    Error(String),
}

fn check_status(status: Status) {
    match status {
        Status::Connected => println!("Connected"),
        Status::Disconnected => println!("Disconnected"),
        Status::Error(msg) => println!("Error: {}", msg),
    }
}

// Option and Result handling
fn read_file_content(path: &Path) -> Result<String, io::Error> {
    let mut file = File::open(path)?;
    let mut content = String::new();
    file.read_to_string(&mut content)?;
    Ok(content)
}

fn safe_divide(a: f64, b: f64) -> Option<f64> {
    if b == 0.0 {
        None
    } else {
        Some(a / b)
    }
}

// Closure and iterator examples
fn process_numbers(numbers: Vec<i32>) -> Vec<i32> {
    numbers
        .iter()
        .filter(|&&x| x > 0)
        .map(|&x| x * 2)
        .collect()
}

// HashMap usage
fn count_words(text: &str) -> HashMap<String, u32> {
    let mut counts = HashMap::new();
    for word in text.split_whitespace() {
        *counts.entry(word.to_string()).or_insert(0) += 1;
    }
    counts
}

// Async function (requires async-std or tokio)
async fn fetch_data(url: &str) -> Result<String, reqwest::Error> {
    let response = reqwest::get(url).await?;
    let text = response.text().await?;
    Ok(text)
}

// Generic function
fn print_vec<T: std::fmt::Debug>(vec: &Vec<T>) {
    for item in vec {
        println!("{:?}", item);
    }
}

// Error handling with custom error type
#[derive(Debug)]
enum AppError {
    IoError(io::Error),
    ParseError(std::num::ParseIntError),
}

impl From<io::Error> for AppError {
    fn from(err: io::Error) -> Self {
        AppError::IoError(err)
    }
}

impl From<std::num::ParseIntError> for AppError {
    fn from(err: std::num::ParseIntError) -> Self {
        AppError::ParseError(err)
    }
}

fn main() {
    let person = Person::new(String::from("Alice"), 30);
    println!("{}", person.display_name());
    
    let numbers = vec![1, 2, 3, 4, 5];
    let doubled = process_numbers(numbers);
    println!("{:?}", doubled);
    
    let text = "hello world hello rust";
    let counts = count_words(text);
    println!("{:?}", counts);
    
    match safe_divide(10.0, 2.0) {
        Some(result) => println!("Result: {}", result),
        None => println!("Division by zero"),
    }
}
