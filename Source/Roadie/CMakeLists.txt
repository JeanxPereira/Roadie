# onyx_install_assets reads PROJECT_SOURCE_DIR when called, which is Roadie's root here, not OnyxSDK's;
# point it at the fetched SDK for the call (a directory-scope variable, the SDK itself stays unpatched).
set(PROJECT_SOURCE_DIR "${onyxsdk_SOURCE_DIR}")

# The verbs and the install-path resolution, shared by the executable and the unit tests.
add_library(RoadieVerbs STATIC Verbs.cpp InstallPath.cpp)
target_include_directories(RoadieVerbs PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(RoadieVerbs PUBLIC Onyx::Core Brutal::Module)
target_link_libraries(RoadieVerbs PRIVATE zlibstatic)  # crc32 for the parity digest
set_target_properties(RoadieVerbs PROPERTIES CXX_SCAN_FOR_MODULES OFF)

add_executable(roadie Main.cpp)
target_link_libraries(roadie PRIVATE Onyx::Shell Onyx::Exchange Brutal::Module RoadieVerbs)
set_target_properties(roadie PROPERTIES CXX_SCAN_FOR_MODULES OFF)
onyx_install_assets(roadie)