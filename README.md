py-adb-mirror

A lightweight Python-based Android screen mirroring tool that works by capturing the device screen using adb screencap, pulling the image to your computer, and displaying it in a browser.
It also supports touch input, including taps and swipes, directly from the web interface.

Note: This project is mostly AI-generated and has been tested on a cheap 4G Android 4.4 device using EndeavourOS.
Due to the simple mirroring method (continuous screencaps), performance will vary by device.

Features

Screen mirroring via repeated adb screencap

Automatic pulling & cleanup of screenshots

Web interface for viewing the live screen

Touch input: taps and swipes

Simple Flask-based backend

Runs fully locally

Requirements
Python Libraries

Install required libraries using:

pip install flask flask-cors pillow

System Requirements

adb must be available in your system PATH

An Android device with USB debugging enabled

Reasonable USB connection speed for frequent screencaps

Usage

Ensure ADB is installed and available globally in your PATH.
(Test with: adb devices)

Connect your Android device via USB.

Launch the Python script:

python main.py


Open your browser and go to:

http://localhost:5000/


You will see the mirrored screen and can interact using taps or swipes.

Notes

This project uses a simple screencap-pull-display loop, not a high-performance video stream.

Compatible with older Android versions (tested on Android 4.4).

Works on EndeavourOS but should run on any Linux, macOS, or Windows system with ADB installed.
