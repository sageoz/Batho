📁 backend/
  📄 app.py
    - get_users() -> list[User] (function) [L6-8]
    - get_product(product_id: int) -> Product | None (function) [L11-13]
    - AppConfig (class) [L16-20]
  📄 models.py
    - User (class) [L4-12]
    - __init__(self, name: str, email: str) -> dict (method) [L7-9]
    - to_dict(self) -> dict (method) [L11-12]
    - Product (class) [L15-20]
    - __init__(self, title: str, price: float) -> dict (method) [L18-20]
    - AdminUser (class) [L23-28]
    - __init__(self, name: str, email: str, role: str = "admin") -> dict (method) [L26-28]
📁 frontend/
  📄 package.json
    - root (section) [L1-1]
    - root.name (setting) [L1-1]
    - root.version (setting) [L1-1]
    - root.dependencies (section) [L1-1]
    - root.dependencies.react (setting) [L1-1]
    - root.dependencies.react-dom (setting) [L1-1]
    - root.devDependencies (section) [L1-1]
    - root.devDependencies.typescript (setting) [L1-1]
    - root.devDependencies.vite (setting) [L1-1]
    - root.devDependencies.@types/react (setting) [L1-1]
  📄 tsconfig.json
    - root (section) [L1-1]
    - root.compilerOptions (section) [L1-1]
    - root.compilerOptions.target (setting) [L1-1]
    - root.compilerOptions.module (setting) [L1-1]
    - root.compilerOptions.jsx (setting) [L1-1]
    - root.compilerOptions.strict (setting) [L1-1]
    - root.compilerOptions.outDir (setting) [L1-1]
    - root.include (section) [L1-1]
    - root.include.[0] (setting) [L1-1]
📁 frontend/src/ (Source Code)
  📄 App.tsx
    - AppProps (interface) [L4-6]
    - App({ title }) (function) [L8-15]
  📄 utils.ts
    - formatDate(date: Date) -> : string (function) [L1-3]
    - capitalize(str: string) -> : string (function) [L5-7]