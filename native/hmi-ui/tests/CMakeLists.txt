# C unit tests for hmi-ui: one executable per test_*.c, registered with
# ctest. Each uses tests/check.h (tiny assert macros); a test that runs 0
# checks fails. HMI_REPO_ROOT points at the checkout for fixtures.
get_filename_component(HMI_REPO_ROOT "${CMAKE_SOURCE_DIR}/../.." ABSOLUTE)

set(HMI_UI_TESTS
    test_model
    test_bind
    test_alarms
)

foreach(name IN LISTS HMI_UI_TESTS)
    add_executable(${name} ${name}.c)
    target_link_libraries(${name} PRIVATE hmi-ui-core)
    target_compile_definitions(${name} PRIVATE HMI_REPO_ROOT="${HMI_REPO_ROOT}")
    target_include_directories(${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ${name} COMMAND ${name})
    set_tests_properties(${name} PROPERTIES TIMEOUT 120)
endforeach()
