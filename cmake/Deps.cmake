include(FetchContent)

FetchContent_Declare(OnyxSDK
    GIT_REPOSITORY https://github.com/JeanxPereira/OnyxSDK.git
    GIT_TAG        v2.0.0)

FetchContent_Declare(zlib
    GIT_REPOSITORY https://github.com/madler/zlib.git
    GIT_TAG        v1.3.1)

set(ZLIB_BUILD_EXAMPLES OFF)  # its `example` test would join our ctest run
FetchContent_MakeAvailable(OnyxSDK zlib)

if(NOT TARGET doctest::doctest)
    FetchContent_Declare(doctest
        GIT_REPOSITORY https://github.com/doctest/doctest.git
        GIT_TAG        v2.4.11)
    set(CMAKE_POLICY_VERSION_MINIMUM 3.5)  # doctest 2.4.11 declares an older minimum than CMake 4 accepts
    FetchContent_MakeAvailable(doctest)
endif()
