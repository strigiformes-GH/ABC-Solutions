from html.parser import HTMLParser


class FormLabelParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.labels = set()
        self.controls = []
        self.label_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "label":
            self.label_depth += 1
            if attributes.get("for"):
                self.labels.add(attributes["for"])
        if tag in {"input", "select", "textarea"} and attributes.get("type") != "hidden":
            self.controls.append((attributes, self.label_depth > 0))

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth -= 1


def test_t24_key_pages_have_titles_and_labeled_controls(client, make_user, login_as):
    login_as(make_user("Manager"))
    for path in ("/app/inventory", "/app/customers", "/app/sales/new", "/app/reports"):
        response = client.get(path)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        parser = FormLabelParser()
        parser.feed(html)
        assert "<title>" in html and "</title>" in html
        for control, has_implicit_label in parser.controls:
            assert (
                control.get("aria-label")
                or control.get("id") in parser.labels
                or has_implicit_label
            )
