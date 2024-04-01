function toggleDeleteButtons() {
    const deleteForms = document.getElementsByClassName("delete-form");
    for (let i = 0; i < deleteForms.length; i++) {
        deleteForms[i].style.display = deleteForms[i].style.display === "none" ? "inline" : "none";
    }
}
