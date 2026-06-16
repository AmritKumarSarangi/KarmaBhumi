cmake_minimum_required(VERSION 3.20)
project(ExchangeMatchingEngine CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find Protobuf and gRPC
find_package(Protobuf REQUIRED)
find_package(Threads REQUIRED)

find_package(PkgConfig REQUIRED)
pkg_check_modules(GRPC REQUIRED IMPORTED_TARGET grpc++)

# Protobuf compiler and gRPC plugin paths
if(NOT PROTOBUF_PROTOC_EXECUTABLE)
    find_program(PROTOBUF_PROTOC_EXECUTABLE protoc)
endif()
if(NOT GRPC_CPP_PLUGIN_EXECUTABLE)
    find_program(GRPC_CPP_PLUGIN_EXECUTABLE grpc_cpp_plugin)
endif()

message(STATUS "Using protoc: ${PROTOBUF_PROTOC_EXECUTABLE}")
message(STATUS "Using grpc_cpp_plugin: ${GRPC_CPP_PLUGIN_EXECUTABLE}")

# Set generated directory
get_filename_component(PROTO_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../proto" REALPATH)
set(GEN_DIR "${CMAKE_CURRENT_BINARY_DIR}/gen")
file(MAKE_DIRECTORY ${GEN_DIR})

message(STATUS "PROTO_SRC_DIR resolved to: ${PROTO_SRC_DIR}")

set(PROTO_FILE "${PROTO_SRC_DIR}/exchange.proto")
message(STATUS "PROTO_FILE resolved to: ${PROTO_FILE}")
set(PROTO_GEN_SRC "${GEN_DIR}/exchange.pb.cc")
set(PROTO_GEN_HDR "${GEN_DIR}/exchange.pb.h")
set(GRPC_GEN_SRC "${GEN_DIR}/exchange.grpc.pb.cc")
set(GRPC_GEN_HDR "${GEN_DIR}/exchange.grpc.pb.h")

# Custom command to run protoc and grpc plugins
add_custom_command(
    OUTPUT "${PROTO_GEN_SRC}" "${PROTO_GEN_HDR}" "${GRPC_GEN_SRC}" "${GRPC_GEN_HDR}"
    COMMAND ${PROTOBUF_PROTOC_EXECUTABLE}
    ARGS --proto_path=${PROTO_SRC_DIR}
         --cpp_out=${GEN_DIR}
         --grpc_out=${GEN_DIR}
         --plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN_EXECUTABLE}
         ${PROTO_FILE}
    DEPENDS "${PROTO_FILE}"
    COMMENT "Generating Protobuf/gRPC stubs from exchange.proto"
    VERBATIM
)

# Header search paths
include_directories(
    src
    ${GEN_DIR}
    ${Protobuf_INCLUDE_DIRS}
)

# Target executable
add_executable(exchange_engine
    src/main.cpp
    src/matching_engine.cpp
    src/order_book.cpp
    src/risk_engine.cpp
    src/grpc_server.cpp
    src/kafka_producer.cpp
    src/metrics.cpp
    ${PROTO_GEN_SRC}
    ${PROTO_GEN_HDR}
    ${GRPC_GEN_SRC}
    ${GRPC_GEN_HDR}
)

# Link libraries
target_link_libraries(exchange_engine
    PRIVATE
    PkgConfig::GRPC
    protobuf::libprotobuf
    rdkafka
    Threads::Threads
)

# Set runtime settings if required
if(UNIX)
    target_link_libraries(exchange_engine PRIVATE dl)
endif()
