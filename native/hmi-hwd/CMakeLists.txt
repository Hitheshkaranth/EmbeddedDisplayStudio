# native/hmi-hwd -- the hardware daemon (Layer 1) in C.
#
# The C port of daemon/hmi_hwd.py plus the panel's peripherals (USB serial,
# Modbus RTU, CAN, HID scanners, USB storage, I2C/SPI sensors); docs/CONTRACT.md
# sections 2, 13.4 and 14. cJSON is shared with hmi-ui (MIT); the historian
# uses the system SQLite.
#
# Build (WSL, x86):               native/hmi-hwd/build.sh [--test]
# Build for the panel (aarch64):  native/hmi-hwd/arm64/build.sh  (bookworm chroot)
cmake_minimum_required(VERSION 3.22)
project(hmi-hwd VERSION 0.2.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
add_compile_options(-Wall -Wextra -Wno-unused-parameter)
add_compile_definitions(_GNU_SOURCE)

find_package(PkgConfig REQUIRED)
pkg_check_modules(SQLITE REQUIRED sqlite3)
find_package(Threads REQUIRED)

set(CJSON_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../hmi-ui/third_party/cjson)
add_library(hwd_cjson STATIC ${CJSON_DIR}/cJSON.c)
target_include_directories(hwd_cjson PUBLIC ${CJSON_DIR})

add_library(hwd-core STATIC
    src/util.c src/tagstore.c src/config.c src/proto.c src/subs.c src/daemon.c
    src/io.c src/serial.c src/modbus.c src/can.c src/hid.c src/usb.c src/sensors.c
    src/history.c)
target_include_directories(hwd-core PUBLIC src ${SQLITE_INCLUDE_DIRS})
target_link_libraries(hwd-core PUBLIC hwd_cjson ${SQLITE_LIBRARIES} Threads::Threads m)

add_executable(hmi-hwd src/main.c)
target_link_libraries(hmi-hwd PRIVATE hwd-core)

enable_testing()
foreach(t test_core test_modbus test_can test_io test_periph)
    add_executable(${t} tests/${t}.c tests/check.h)
    target_link_libraries(${t} PRIVATE hwd-core util)
    add_test(NAME ${t} COMMAND ${t})
    set_tests_properties(${t} PROPERTIES TIMEOUT 60)
endforeach()
