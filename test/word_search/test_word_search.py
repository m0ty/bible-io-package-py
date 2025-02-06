

def test_find_word(bible):
    word_index_list = bible.find_word("Moses")

    for wi in word_index_list:
        print(wi)