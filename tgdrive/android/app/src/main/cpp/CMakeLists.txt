cmake_minimum_required(VERSION 3.22.1)
project(tgdrive_native C)

# SQLite's FTS5 as a loadable extension (see sqlite/README.md). It calls SQLite only through the
# API table SQLite hands it, so it links against nothing but libc.
add_library(tgfts5 SHARED sqlite/fts5.c)
target_include_directories(tgfts5 PRIVATE sqlite)
target_compile_options(tgfts5 PRIVATE -O2 -Wno-unused-function -Wno-unused-variable)
target_link_options(tgfts5 PRIVATE -Wl,-z,max-page-size=16384)
