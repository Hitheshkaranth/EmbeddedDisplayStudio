# native/hmi-gui -- the panel GUI loader (Layer 2) as a native Qt 6 executable.
#
# Replaces gui/hmi_loader/main.py + tagengine.py on the panel. Same CLI flags,
# same UDP wire protocol, same QML API (Tags / Bus / BusImpl / Hmi), same
# install path (/usr/lib/hmi/gui/hmi-gui beside the Python files it retires).
# The QML shell and the Shadcn kit are still loaded from the filesystem at the
# CONTRACT section 3 paths, so bundles, the Designer and the AI generator are
# untouched by this port.
#
# Build (WSL / Linux):   native/hmi-gui/build.sh --test
# Build (Windows host):  powershell -File native/hmi-gui/build.ps1 --test

cmake_minimum_required(VERSION 3.22)
project(hmi-gui VERSION 2.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Qt6 6.4 REQUIRED COMPONENTS Core Gui Qml Quick Network)

# Everything except main() lives in a static library so the unit tests link
# the real objects rather than re-compiling sources per test.
add_library(hmi-gui-core STATIC
    src/log.cpp
    src/manifest.cpp
    src/hmi.cpp
    src/busshim.cpp
    src/tagmap.cpp
    src/tagengine.cpp
    src/history.cpp
    src/alarmengine.cpp
)
target_include_directories(hmi-gui-core PUBLIC src)
target_link_libraries(hmi-gui-core PUBLIC
    Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick Qt6::Network)
target_compile_options(hmi-gui-core PRIVATE -Wall -Wextra)

add_executable(hmi-gui src/main.cpp)
target_link_libraries(hmi-gui PRIVATE hmi-gui-core)
target_compile_options(hmi-gui PRIVATE -Wall -Wextra)

# CONTRACT section 3: /usr/lib/hmi/gui/. The launcher execs this path when it
# exists and falls back to main.py otherwise, so both can coexist on a panel.
install(TARGETS hmi-gui DESTINATION lib/hmi/gui)

enable_testing()
add_subdirectory(tests)
