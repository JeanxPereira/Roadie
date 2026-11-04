cmake_minimum_required(VERSION 4.0)
project(Roadie CXX C)

set(CMAKE_CXX_STANDARD 26)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/$<CONFIG>)
if(MSVC)
    add_compile_options(/utf-8)
endif()

set(ONYX_WITH_MEDIA OFF)  # Roadie plays no audio yet
include(cmake/Deps.cmake)

enable_testing()
add_subdirectory(Source/Brutal)
add_subdirectory(Source/Roadie)
add_subdirectory(Tests/Unit)
