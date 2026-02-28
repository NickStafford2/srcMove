cmake_minimum_required(VERSION 3.20)
project(srcMove LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Allow building in your workspace where these are sibling dirs.
# You can override these at configure time with -D... if needed.
set(WORKSPACE_ROOT "" CACHE PATH "Workspace root that contains srcReader and srcML-install")

if(WORKSPACE_ROOT STREQUAL "")
  # assume srcMove is in WORKSPACE_ROOT/srcMove
  get_filename_component(WORKSPACE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
endif()

set(SRCREADER_ROOT "${WORKSPACE_ROOT}/srcReader" CACHE PATH "Path to srcReader repo")
set(SRCML_INSTALL_PREFIX "${WORKSPACE_ROOT}/srcML-install" CACHE PATH "srcML install prefix")

# Dependencies
find_package(LibXml2 REQUIRED)

add_executable(srcMovesrc/main.cpp)

target_include_directories(srcMove PRIVATE
  "${SRCREADER_ROOT}/src"
  "${SRCML_INSTALL_PREFIX}/include"
  ${LIBXML2_INCLUDE_DIR}
)

target_link_directories(srcMove PRIVATE
  "${SRCREADER_ROOT}/build/bin"
  "${SRCML_INSTALL_PREFIX}/lib"
)

# Link srcreader + srcml + libxml2
target_link_libraries(srcMove PRIVATE
  srcreader
  srcml
  ${LIBXML2_LIBRARIES}
)

# Make runtime loading work without setting LD_LIBRARY_PATH
set_target_properties(srcMove PROPERTIES
  BUILD_RPATH "${SRCREADER_ROOT}/build/bin;${SRCML_INSTALL_PREFIX}/lib"
)
