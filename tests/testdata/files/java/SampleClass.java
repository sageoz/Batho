// Sample Java code for testing language detection

import java.io.*;
import java.util.*;
import java.util.stream.Collectors;
import java.nio.file.*;

public class SampleClass {
    private String name;
    private int age;
    private String privateData;
    
    // Constructor
    public SampleClass(String name, int age) {
        this.name = name;
        this.age = age;
        this.privateData = "private";
    }
    
    // Getters and setters
    public String getName() {
        return name;
    }
    
    public void setName(String name) {
        this.name = name;
    }
    
    public int getAge() {
        return age;
    }
    
    public void setAge(int age) {
        this.age = age;
    }
    
    // Instance method
    public String displayName() {
        return "Person: " + name;
    }
    
    // Static method
    public static int add(int a, int b) {
        return a + b;
    }
    
    // Method with exceptions
    public String readFile(String filePath) throws IOException {
        Path path = Paths.get(filePath);
        return Files.readString(path);
    }
    
    // Interface implementation
    public interface Shape {
        double area();
        double perimeter();
    }
    
    public static class Rectangle implements Shape {
        private double width;
        private double height;
        
        public Rectangle(double width, double height) {
            this.width = width;
            this.height = height;
        }
        
        @Override
        public double area() {
            return width * height;
        }
        
        @Override
        public double perimeter() {
            return 2 * (width + height);
        }
    }
    
    // Generic method
    public static <T> void printList(List<T> list) {
        for (T item : list) {
            System.out.println(item);
        }
    }
    
    // Stream API usage
    public static List<Integer> processNumbers(List<Integer> numbers) {
        return numbers.stream()
                .filter(n -> n > 0)
                .map(n -> n * 2)
                .collect(Collectors.toList());
    }
    
    // Exception handling
    public static Optional<Integer> safeDivide(int a, int b) {
        try {
            return Optional.of(a / b);
        } catch (ArithmeticException e) {
            return Optional.empty();
        }
    }
    
    // Enum
    public enum Status {
        CONNECTED("Connected"),
        DISCONNECTED("Disconnected"),
        ERROR("Error");
        
        private final String description;
        
        Status(String description) {
            this.description = description;
        }
        
        public String getDescription() {
            return description;
        }
    }
    
    // HashMap usage
    public static Map<String, Integer> countWords(String text) {
        Map<String, Integer> counts = new HashMap<>();
        String[] words = text.split("\\s+");
        
        for (String word : words) {
            counts.put(word, counts.getOrDefault(word, 0) + 1);
        }
        
        return counts;
    }
    
    // Main method
    public static void main(String[] args) {
        SampleClass person = new SampleClass("Alice", 30);
        System.out.println(person.displayName());
        
        List<Integer> numbers = Arrays.asList(1, 2, 3, 4, 5);
        List<Integer> doubled = processNumbers(numbers);
        System.out.println(doubled);
        
        String text = "hello world hello java";
        Map<String, Integer> counts = countWords(text);
        System.out.println(counts);
        
        Optional<Integer> result = safeDivide(10, 2);
        result.ifPresent(r -> System.out.println("Result: " + r));
        
        Status status = Status.CONNECTED;
        System.out.println("Status: " + status.getDescription());
    }
}
