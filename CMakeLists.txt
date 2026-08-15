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
set(SRCREADER_BUILD_DIR "${SRCREADER_ROOT}/build" CACHE PATH "Path to the srcReader build directory")
set(SRCML_INSTALL_PREFIX "${WORKSPACE_ROOT}/srcML-install" CACHE PATH "srcML install prefix")

find_package(LibXml2 REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

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
  "${SRCREADER_BUILD_DIR}/bin"
  "${SRCML_INSTALL_PREFIX}/lib"
)

set(COMMON_LIBS
  srcreader
  srcml
  ${LIBXML2_LIBRARIES}
)

set(COMMON_RPATH
  "${SRCREADER_BUILD_DIR}/bin;${SRCML_INSTALL_PREFIX}/lib"
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
  "${CMAKE_CURRENT_SOURCE_DIR}/src/parse/*.cpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/src/writer/*.cpp"
)

add_executable(srcMove ${SRC_FILES})
configure_srcmove_target(srcMove)

set(SRCMOVE_RECEIPT_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/benchmarks/emit_build_receipt.py")
set(SRCMOVE_SOURCE_LOCK "${WORKSPACE_ROOT}/workspace.lock.json")
set(SRCMOVE_BUILD_ENTRY_POINT "cmake --build ${CMAKE_BINARY_DIR} --target srcMove")
if(CMAKE_BUILD_TYPE STREQUAL "")
  set(SRCMOVE_BUILD_CONFIGURATION "Unspecified")
else()
  set(SRCMOVE_BUILD_CONFIGURATION "${CMAKE_BUILD_TYPE}")
endif()
set(SRCMOVE_CMAKE_OPTIONS
  "{\"build_type\":\"${CMAKE_BUILD_TYPE}\",\"cxx_standard\":\"${CMAKE_CXX_STANDARD}\"}"
)

add_custom_command(TARGET srcMove POST_BUILD
  COMMAND "${Python3_EXECUTABLE}" "${SRCMOVE_RECEIPT_SCRIPT}"
    --output "$<TARGET_FILE:srcMove>.build-receipt.json"
    --artifact "$<TARGET_FILE:srcMove>"
    --repository "srcMove=${CMAKE_CURRENT_SOURCE_DIR}"
    --repository "srcReader=${SRCREADER_ROOT}"
    --source-lock "${SRCMOVE_SOURCE_LOCK}"
    --build-entry-point "${SRCMOVE_BUILD_ENTRY_POINT}"
    --configuration "${SRCMOVE_BUILD_CONFIGURATION}"
    --cmake-options "${SRCMOVE_CMAKE_OPTIONS}"
    --compiler-id "${CMAKE_CXX_COMPILER_ID}"
    --compiler-version "${CMAKE_CXX_COMPILER_VERSION}"
    --test-status not_run
  COMMENT "Writing srcMove build receipt"
  VERBATIM
)

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
