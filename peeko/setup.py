from setuptools import setup, find_packages

setup(
    name="peeko",
    version="1.3.0",
    description="Peeko - Serial-based MCU RAM read/write tool",
    author="zhangfeibao",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "click>=8.0",
        "pyserial>=3.5",
        "prompt_toolkit>=3.0",
        "pyelftools>=0.30",
    ],
    entry_points={
        "console_scripts": [
            "peeko=peeko.cli:cli",
        ],
    },
)
