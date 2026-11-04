# onyx_install_assets reads PROJECT_SOURCE_DIR when called, which is Roadie's root here, not OnyxSDK's;
# point it at the fetched SDK for the call (a directory-scope variable, the SDK itself stays unpatched).
set(PROJECT_SOURCE_DIR "${onyxsdk_SOURCE_DIR}")

add_executable(roadie Main.cpp)
target_link_libraries(roadie PRIVATE Onyx::Shell Onyx::Exchange Brutal::Module)
set_target_properties(roadie PROPERTIES CXX_SCAN_FOR_MODULES OFF)
onyx_install_assets(roadie)