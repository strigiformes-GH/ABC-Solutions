// interactivity of the sale form


(() => {
  const lineList = document.querySelector("#sale-lines");
  const addButton = document.querySelector("#add-sale-line");

  if (!lineList || !addButton) {
    // check for sale form
    return;
  }

  // update rows after add/delete
  function updateRows() {
    const rows = lineList.querySelectorAll(".sale-line");
    rows.forEach((row, index) => {
      const rowNumber = index + 1;
      // correct item and quanities
      row.querySelectorAll("label").forEach((label) => {
        if (label.htmlFor.startsWith("sale-item-")) {
          label.htmlFor = `sale-item-${rowNumber}`;
          label.textContent = `Item ${rowNumber}`;
        } else {
          label.htmlFor = `sale-quantity-${rowNumber}`;
          label.textContent = `Quantity ${rowNumber}`;
        }
      });
      // match id to label
      row.querySelector('select[name="item_id"]').id = `sale-item-${rowNumber}`;
      row.querySelector('input[name="quantity"]').id =
        `sale-quantity-${rowNumber}`;
      // hide remove btn if there is one row
      const removeButton = row.querySelector(".remove-sale-line");
      removeButton.hidden = rows.length === 1;
    });
  }
  
  // copy first row when add item
  addButton.addEventListener("click", () => {
    const firstRow = lineList.querySelector(".sale-line");
    const newRow = firstRow.cloneNode(true);

    newRow.querySelector('select[name="item_id"]').selectedIndex = 0;
    newRow.querySelector('input[name="quantity"]').value = "";
    // put new row in form and update label/id
    lineList.appendChild(newRow);
    updateRows();
  });

  // remove btn clicks
  lineList.addEventListener("click", (event) => {
    const removeButton = event.target.closest(".remove-sale-line");
    const rows = lineList.querySelectorAll(".sale-line");
    if (removeButton && rows.length > 1) {
      removeButton.closest(".sale-line").remove();
      updateRows(); //renumber after removal
    }
  });
  
  // set labels and btns on page load
  updateRows();
})();
