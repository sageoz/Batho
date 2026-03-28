from setuptools import setup, find_packages

setup(
    name="simple-python",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["requests>=2.28.0"],
    python_requires=">=3.10",
)
