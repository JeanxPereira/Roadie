add_executable(RoadieUnit Main.cpp ModuleTests.cpp)
target_link_libraries(RoadieUnit PRIVATE Brutal::Module doctest::doctest)
set_target_properties(RoadieUnit PROPERTIES CXX_SCAN_FOR_MODULES OFF)
add_test(NAME Unit COMMAND RoadieUnit)
