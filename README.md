# browse-cli

CLI tools to help LLM agents browse the web.
Thin wrapper around playwright's accessibility tree.

Uses code from [webarena](https://github.com/web-arena-x/webarena) to process the accessibility tree.

Usage:

The cli interface assumes implicit context.
To do this, you need to start a server before connecting.


To start the server:
```
browse-start
```

Once the server is started, you can use the rest of the commands.
If the server is not started, they will error when you try to use them.

Browse commands:

To open a URL in the browser:
```
Usage: browse-goto [OPTIONS] URL

  Goes to the url URL

Options:
  --help  Show this message and exit.
```

To click an element:
```
Usage: browse-click [OPTIONS] ID

  Clicks on the element ID

Options:
  --help  Show this message and exit.
```

To type in text and (optionally) hit enter:
```
Usage: browse-type [OPTIONS] ID TEXT

  Types the text TEXT in the element ID

Options:
  --enter
  --help   Show this message and exit.
```

To scroll up or down in the page:
```
Usage: browse-scroll [OPTIONS] {up|down}

  Scrolls the page in the DIRECTION direction

Options:
  --help  Show this message and exit.
```

To navigate in browser history:
```
Usage: browse-navigate [OPTIONS] {back|forward}

  Navigates browser history in the DIRECTION direction

Options:
  --help  Show this message and exit.
```

To view the page contents again:
```
Usage: browse-observe [OPTIONS]

  Observes the page

Options:
  --help  Show this message and exit.
```

To reload the page:
```
Usage: browse-reload [OPTIONS]

  Reloads the page

Options:
  --help  Show this message and exit.
```
