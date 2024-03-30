function toggleDeleteButtons() {
    const deleteForms = document.getElementsByClassName("delete-form");
    for (let i = 0; i < deleteForms.length; i++) {
        if (deleteForms[i].style.display === "none") {
            deleteForms[i].style.display = "inline";
        } else {
            deleteForms[i].style.display = "none";
        }
    }
}