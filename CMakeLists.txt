cmake_minimum_required(VERSION 3.20)
project(srcMove LANGUAGES CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ------------------------------------------------------------
# Workspace layout
# ------------------------------------------------------------

set(WORKSPACE_ROOT "" CACHE PATH "Workspace root that contains srcReader and srcML-install")

if(WORKSPACE_ROOT STREQUAL "")
  get_filename_component(WORKSPACE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
endif()

set(SRCREADER_ROOT "${WORKSPACE_ROOT}/srcReader" CACHE PATH "Path to srcReader repo")
set(SRCML_INSTALL_PREFIX "${WORKSPACE_ROOT}/srcML-install" CACHE PATH "srcML install prefix")

find_package(LibXml2 REQUIRED)

# ------------------------------------------------------------
# Common configuration for all binaries
# ------------------------------------------------------------

set(COMMON_INCLUDE_DIRS
  "${CMAKE_CURRENT_SOURCE_DIR}/src"
  "${SRCREADER_ROOT}/src"
  "${SRCML_INSTALL_PREFIX}/include"
  ${LIBXML2_INCLUDE_DIR}
)

set(COMMON_LINK_DIRS
  "${SRCREADER_ROOT}/build/bin"
  "${SRCML_INSTALL_PREFIX}/lib"
)

set(COMMON_LIBS
  srcreader
  srcml
  ${LIBXML2_LIBRARIES}
)

set(COMMON_RPATH
  "${SRCREADER_ROOT}/build/bin;${SRCML_INSTALL_PREFIX}/lib"
)

function(configure_srcmove_target TARGET)
  target_include_directories(${TARGET} PRIVATE ${COMMON_INCLUDE_DIRS})
  target_link_directories(${TARGET} PRIVATE ${COMMON_LINK_DIRS})
  target_link_libraries(${TARGET} PRIVATE ${COMMON_LIBS})

  set_target_properties(${TARGET} PROPERTIES
    BUILD_RPATH "${COMMON_RPATH}"
  )
endfunction()

# ------------------------------------------------------------
# Main srcMove executable
# ------------------------------------------------------------

file(GLOB SRC_FILES CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/src/move_registry/*.cpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/src/writer/*.cpp"
)

add_executable(srcMove ${SRC_FILES})
configure_srcmove_target(srcMove)

# ------------------------------------------------------------
# Debug tools
# ------------------------------------------------------------

add_executable(srcdiff_render
  tools/srcdiff_render.cpp
)
configure_srcmove_target(srcdiff_render)

add_executable(srcdiff_highlight
  tools/srcdiff_highlight.cpp
)
configure_srcmove_target(srcdiff_highlight)

add_executable(srcdiff_highlight_pos
  tools/srcdiff_highlight_pos.cpp
)
configure_srcmove_target(srcdiff_highlight_pos)

# ------------------------------------------------------------
# Unit tests
# ------------------------------------------------------------

enable_testing()

add_executable(test_canonical_subtree_unit
  test/canonical/test_canonical_subtree.cpp
  src/canonical_subtree.cpp
  src/diff_region.cpp
  src/move_candidate.cpp
  src/region_filter.cpp
)

configure_srcmove_target(test_canonical_subtree_unit)

target_compile_definitions(test_canonical_subtree_unit PRIVATE
  SRCMOVE_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
)

add_test(
  NAME canonical_subtree_unit
  COMMAND test_canonical_subtree_unit
)
