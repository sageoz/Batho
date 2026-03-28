// Sample JavaScript/ES6+ code for testing language detection

// Arrow functions
const add = (a, b) => a + b;
const multiply = (a, b) => {
    return a * b;
};

// Template literals
const greeting = (name) => `Hello, ${name}!`;

// Destructuring
const person = {
    name: "John",
    age: 30,
    city: "New York"
};

const { name, age } = person;
const [first, second] = [1, 2, 3];

// Classes
class SampleClass {
    constructor(name) {
        this.name = name;
        this._private = "private";
    }
    
    get displayName() {
        return `Sample: ${this.name}`;
    }
    
    methodWithArgs(...args) {
        return args;
    }
    
    static staticMethod() {
        return "static";
    }
}

// Async/await
async function fetchData() {
    try {
        const response = await fetch('/api/data');
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error:', error);
        return null;
    }
}

// Modules (ES6 import/export)
export const PI = 3.14159;

export function calculateArea(radius) {
    return PI * radius * radius;
}

export default class Calculator {
    add(a, b) {
        return a + b;
    }
    
    subtract(a, b) {
        return a - b;
    }
}

// Array methods and functional programming
const numbers = [1, 2, 3, 4, 5];
const doubled = numbers.map(n => n * 2);
const evens = numbers.filter(n => n % 2 === 0);
const sum = numbers.reduce((acc, n) => acc + n, 0);

// Promises
const promise = new Promise((resolve, reject) => {
    setTimeout(() => {
        resolve('Success!');
    }, 1000);
});

promise.then(result => console.log(result));
