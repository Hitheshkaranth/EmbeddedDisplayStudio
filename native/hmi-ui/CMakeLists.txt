# native/hmi-ui -- the Qt-free panel GUI runtime (C, LVGL 9).
#
# Phase 3 of the native port: a runtime that loads a project's .edsui
# directly, draws it with LVGL straight to DRM/KMS (no Qt, no compositor) and
# speaks the CONTRACT section 2 wire protocol to hmi-hwd. lv_conf.h is the
# LVGL configuration; lvgl/ is the pinned upstream submodule (release/v9.3).
#
# Build (WSL, x86 headless):      native/hmi-ui/build.sh
# Build for the panel (aarch64):  native/hmi-ui/arm64/build.sh  (bookworm chroot)
cmake_minimum_required(VERSION 3.22)
project(hmi-ui VERSION 0.1.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(PkgConfig REQUIRED)
pkg_check_modules(DRM REQUIRED libdrm)

set(LV_BUILD_CONF_PATH "${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h" CACHE PATH "" FORCE)
set(CONFIG_LV_BUILD_DEMOS OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_THORVG_INTERNAL OFF CACHE BOOL "" FORCE)
add_subdirectory(lvgl EXCLUDE_FROM_ALL)
# The DRM driver (src/drivers/display/drm) includes <xf86drm.h>; LVGL's own
# CMake does not add libdrm, so do it here.
target_include_directories(lvgl PUBLIC ${DRM_INCLUDE_DIRS})
target_link_libraries(lvgl PUBLIC ${DRM_LIBRARIES} m)

# spike: an arc + a label on the real display (or a PNG headless).
add_executable(hmi-ui-spike spike/main.c)
target_include_directories(hmi-ui-spike PRIVATE ${CMAKE_CURRENT_SOURCE_DIR} ${DRM_INCLUDE_DIRS})
target_link_libraries(hmi-ui-spike PRIVATE lvgl ${DRM_LIBRARIES} m)
target_compile_options(hmi-ui-spike PRIVATE -Wall -Wextra)
