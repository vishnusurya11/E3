"""
Setup script for E3 ComfyUI Agent.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="e3-comfyui-agent",
    version="1.0.0",
    author="ViSuReNa LLC",
    description="E3 ComfyUI Agent - AI Media Generation Pipeline",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/visurena/e3-comfyui-agent",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Multimedia :: Graphics",
        "Topic :: Multimedia :: Sound/Audio",
        "Topic :: Multimedia :: Video",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "e3=comfyui_agent.cli:app",
        ],
    },
    include_package_data=True,
    package_data={
        "comfyui_agent": [
            "config/*.yaml",
            "static/*.html",
            "static/*.css",
            "static/*.js",
        ],
    },
)