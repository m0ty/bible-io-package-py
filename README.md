# Bible JSON Package

This package provides a comprehensive JSON representation of the Bible. It includes both the Old and New Testaments in a structured format that is easy to parse and use in various applications.

Expected JSON structure:

```
[
    {
        "abbrev": "gn",
        "chapters": [
            [
                "In the beginning God created the heaven and the earth.",
                "And the earth was without form, and void; ...",
                "And God said, Let there be light: and there was light.",
                ...
            ],
            [
                "Thus the heavens and the earth were finished, and all the host of them.",
                "And on the seventh day God ended his work which he had made; ...",
            ],
            ...
        ],
        "name": "Genesis" 
    },
    {
        "abbrev": "ex",
        "chapters": [
            [
                "Now these {are} the names of the children of Israel...",
                "Reuben, Simeon, Levi, and Judah,",
                "Issachar, Zebulun, and Benjamin,",
                ...
            ],
            [
                "And there went a man of the house of Levi, ...",
                "And the woman conceived, and bare a son: ...",
            ],
            ...
        ],
        "name": "Exodus" 
    },
    ...
]
```

## Features

- Complete text of the Bible in JSON format
- Structured data for easy parsing
- Includes both Old and New Testaments

## Installation

To install the package, use the following command:

```
pip install bible-json
```

## Usage

Here is an example of how to use the package in your project:

```python
from bible-json import Bible, BibleVersions, OldTestamentBooks

bible = Bible.new(BibleVersions.EnKingJames)


```

## License

This project is licensed under the MIT License.
