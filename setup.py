from setuptools import setup, find_packages

setup(
    name="dzdk",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click",
        "requests",
        "rich",
        "pyyaml",
        "pandas",
        "tabulate",
        "prompt_toolkit",
    ],
    entry_points={
        "console_scripts": [
            "dzdk=dzdk:cli",
        ],
    },
    author="Dzaleka Digital Heritage",
    author_email="bakari@mail.dzaleka.com",
    description="A CLI tool for interacting with the Dzaleka Digital Heritage API",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://services.dzaleka.com",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    python_requires=">=3.7",
) 