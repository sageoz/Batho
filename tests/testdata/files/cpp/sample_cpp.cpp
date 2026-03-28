// Sample C++ code for testing language detection

#include <iostream>
#include <vector>
#include <string>
#include <map>
#include <algorithm>
#include <fstream>
#include <memory>
#include <optional>
#include <filesystem>

// Simple function
int add(int a, int b) {
    return a + b;
}

// Class with methods
class Person {
private:
    std::string name;
    int age;
    std::string private_data;
    
public:
    // Constructor
    Person(const std::string& name, int age) 
        : name(name), age(age), private_data("private") {}
    
    // Getters and setters
    const std::string& getName() const { return name; }
    void setName(const std::string& newName) { name = newName; }
    
    int getAge() const { return age; }
    void setAge(int newAge) { age = newAge; }
    
    // Instance method
    std::string displayName() const {
        return "Person: " + name;
    }
    
    // Static method
    static int multiply(int a, int b) {
        return a * b;
    }
    
    // Virtual method for polymorphism
    virtual void describe() const {
        std::cout << displayName() << ", Age: " << age << std::endl;
    }
    
    virtual ~Person() = default;
};

// Interface (abstract class)
class Shape {
public:
    virtual double area() const = 0;
    virtual double perimeter() const = 0;
    virtual ~Shape() = default;
};

class Rectangle : public Shape {
private:
    double width;
    double height;
    
public:
    Rectangle(double w, double h) : width(w), height(h) {}
    
    double area() const override {
        return width * height;
    }
    
    double perimeter() const override {
        return 2 * (width + height);
    }
};

// Template function
template <typename T>
void printVector(const std::vector<T>& vec) {
    for (const auto& item : vec) {
        std::cout << item << " ";
    }
    std::cout << std::endl;
}

// Lambda expressions and STL algorithms
std::vector<int> processNumbers(const std::vector<int>& numbers) {
    std::vector<int> result;
    
    std::copy_if(numbers.begin(), numbers.end(), std::back_inserter(result),
                 [](int n) { return n > 0; });
    
    std::transform(result.begin(), result.end(), result.begin(),
                   [](int n) { return n * 2; });
    
    return result;
}

// Optional usage (C++17)
std::optional<int> safeDivide(int a, int b) {
    if (b == 0) {
        return std::nullopt;
    }
    return a / b;
}

// Smart pointers
void demonstrateSmartPointers() {
    // Unique pointer
    auto person = std::make_unique<Person>("Alice", 30);
    std::cout << person->displayName() << std::endl;
    
    // Shared pointer
    auto shared_person = std::make_shared<Person>("Bob", 25);
    auto another_ref = shared_person; // Reference count = 2
    std::cout << shared_person->displayName() << std::endl;
}

// File operations
std::string readFile(const std::string& filePath) {
    std::ifstream file(filePath);
    if (!file.is_open()) {
        throw std::runtime_error("Cannot open file: " + filePath);
    }
    
    std::string content((std::istreambuf_iterator<char>(file)),
                        std::istreambuf_iterator<char>());
    return content;
}

// Map operations
std::map<std::string, int> countWords(const std::string& text) {
    std::map<std::string, int> counts;
    std::istringstream iss(text);
    std::string word;
    
    while (iss >> word) {
        counts[word]++;
    }
    
    return counts;
}

// Namespace usage
namespace Utils {
    namespace Math {
        double average(const std::vector<double>& numbers) {
            if (numbers.empty()) return 0.0;
            
            double sum = std::accumulate(numbers.begin(), numbers.end(), 0.0);
            return sum / numbers.size();
        }
    }
    
    namespace String {
        std::string toUpper(const std::string& str) {
            std::string result = str;
            std::transform(result.begin(), result.end(), result.begin(),
                           ::toupper);
            return result;
        }
    }
}

// Enum class
enum class Status {
    CONNECTED,
    DISCONNECTED,
    ERROR
};

std::string statusToString(Status status) {
    switch (status) {
        case Status::CONNECTED: return "Connected";
        case Status::DISCONNECTED: return "Disconnected";
        case Status::ERROR: return "Error";
        default: return "Unknown";
    }
}

int main() {
    // Basic usage
    Person person("Alice", 30);
    person.describe();
    
    // STL containers
    std::vector<int> numbers = {1, 2, 3, 4, 5};
    auto doubled = processNumbers(numbers);
    printVector(doubled);
    
    // Map usage
    std::string text = "hello world hello cpp";
    auto counts = countWords(text);
    for (const auto& [word, count] : counts) {
        std::cout << word << ": " << count << std::endl;
    }
    
    // Optional usage
    auto result = safeDivide(10, 2);
    if (result) {
        std::cout << "Result: " << *result << std::endl;
    }
    
    // Smart pointers
    demonstrateSmartPointers();
    
    // Namespace usage
    std::vector<double> scores = {85.5, 90.0, 78.5, 92.0};
    double avg = Utils::Math::average(scores);
    std::cout << "Average: " << avg << std::endl;
    
    // Enum usage
    Status status = Status::CONNECTED;
    std::cout << "Status: " << statusToString(status) << std::endl;
    
    // Filesystem (C++17)
    std::filesystem::path currentPath = std::filesystem::current_path();
    std::cout << "Current path: " << currentPath << std::endl;
    
    return 0;
}
