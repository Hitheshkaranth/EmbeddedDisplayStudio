# Unit tests for the native loader. One executable per tst_*.cpp; each is a
# QTest case registered with ctest and run offscreen so it works on a headless
# WSL / CI box.
#
# Adding a test: drop tst_<name>.cpp here and append it to HMI_GUI_TESTS.

find_package(Qt6 6.4 REQUIRED COMPONENTS Test)

set(HMI_GUI_TESTS
    tst_history
    tst_alarms
    tst_manifest
    tst_tagengine
)

foreach(name IN LISTS HMI_GUI_TESTS)
    add_executable(${name} ${name}.cpp)
    target_link_libraries(${name} PRIVATE hmi-gui-core Qt6::Test)
    add_test(NAME ${name} COMMAND ${name})
    set_tests_properties(${name} PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        TIMEOUT 120)
endforeach()
