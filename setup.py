from setuptools import setup, find_packages

setup(
    name="swarm-ai",
    version="0.1.0",
    description="Open-source runtime that distributes local AI workloads across multiple computers",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Channu Praveen",
    url="https://github.com/YOUR_USERNAME/swarm-ai",
    py_modules=["swarm", "worker"],
    python_requires=">=3.10",
    install_requires=[
        "fastapi>=0.104.0",
        "uvicorn>=0.24.0",
        "httpx>=0.25.0",
        "typer>=0.9.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "swarm=swarm:app",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
