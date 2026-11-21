cmake_minimum_required(VERSION 3.18)
project(ParallelWarehouseEngine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")

# Always build serial baseline
add_executable(engine_serial engine.cpp)
set_target_properties(engine_serial PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}"
    RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}"
)

# OpenMP target
find_package(OpenMP)
if(OpenMP_CXX_FOUND)
    add_executable(engine_omp engine.cpp)
    target_link_libraries(engine_omp PRIVATE OpenMP::OpenMP_CXX)
    set_target_properties(engine_omp PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}"
        RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}"
    )
    message(STATUS "OpenMP found: building engine_omp")
endif()

# MPI + OpenMP target
find_package(MPI)
if(MPI_CXX_FOUND)
    add_executable(engine_mpi engine.cpp)
    target_compile_definitions(engine_mpi PRIVATE USE_MPI)
    target_link_libraries(engine_mpi PRIVATE MPI::MPI_CXX)
    if(OpenMP_CXX_FOUND)
        target_link_libraries(engine_mpi PRIVATE OpenMP::OpenMP_CXX)
    endif()
    set_target_properties(engine_mpi PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}"
        RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}"
    )
    message(STATUS "MPI found: building engine_mpi")
endif()
