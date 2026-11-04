add_library(CorpusSupport STATIC Support/Corpus.cpp)
target_include_directories(CorpusSupport PUBLIC Support)
target_link_libraries(CorpusSupport PUBLIC Brutal::Module)
set_target_properties(CorpusSupport PROPERTIES CXX_SCAN_FOR_MODULES OFF)

# One executable per gate; the exit code is the verdict. They need the game install (BL_GAME_DIR) and
# carry the `corpus` label so CI and `ctest -LE corpus` skip them.
function(corpus_gate name source)
    add_executable(${name} ${source})
    target_link_libraries(${name} PRIVATE CorpusSupport)
    set_target_properties(${name} PROPERTIES CXX_SCAN_FOR_MODULES OFF)
    add_test(NAME ${name} COMMAND ${name})
    set_tests_properties(${name} PROPERTIES LABELS corpus)
endfunction()

corpus_gate(DfpfGate DfpfGate.cpp)
corpus_gate(TextureGate TextureGate.cpp)
