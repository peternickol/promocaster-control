document.addEventListener("DOMContentLoaded",function(){var e=document.getElementById("show-hide-column");if(e){let o=new DataTable(e,{responsive:!0,dom:"<'md:flex justify-between items-center mb-3'<'columnToggleWrapper'B>f>rt<'md:flex justify-between items-center mt-base'lp>",language:{paginate:{first:'<svg  xmlns="http://www.w3.org/2000/svg"  width="24"  height="24"  viewBox="0 0 24 24"  fill="none"  stroke="currentColor"  stroke-width="2"  stroke-linecap="round"  stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M11 7l-5 5l5 5" /><path d="M17 7l-5 5l5 5" /></svg>',previous:'<svg  xmlns="http://www.w3.org/2000/svg"  width="24"  height="24"  viewBox="0 0 24 24"  fill="none"  stroke="currentColor"  stroke-width="2"  stroke-linecap="round"  stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M15 6l-6 6l6 6" /></svg>',next:'<svg  xmlns="http://www.w3.org/2000/svg"  width="24"  height="24"  viewBox="0 0 24 24"  fill="none"  stroke="currentColor"  stroke-width="2"  stroke-linecap="round"  stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M9 6l6 6l-6 6" /></svg>',last:'<svg  xmlns="http://www.w3.org/2000/svg"  width="24"  height="24"  viewBox="0 0 24 24"  fill="none"  stroke="currentColor"  stroke-width="2"  stroke-linecap="round"  stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M7 7l5 5l-5 5" /><path d="M13 7l5 5l-5 5" /></svg>'}}});var t,e=["Company","Symbol","Price","Change","Volume","Market Cap","Rating","Status"],n=document.querySelector(".columnToggleWrapper");n&&((t=document.createElement("div")).className="hs-dropdown [--auto-close:inside] relative inline-flex",t.innerHTML=`
        <button class="hs-dropdown-toggle btn btn-sm bg-secondary text-white" type="button">
            Show/Hide Columns
        </button>
        <ul class="hs-dropdown-menu" id="columnToggleMenu">
            ${e.map((e,t)=>`
                <li class="dropdown-item">
                    <div class="flex items-center gap-2">
                        <input class="form-checkbox form-checkbox-light mt-0 toggle-vis" 
                               type="checkbox" data-column="${t}" id="colToggle${t}" checked>
                        <label class="form-check-label font-medium" for="colToggle${t}">
                            ${e}
                        </label>
                    </div>
                </li>
            `).join("")}
        </ul>
    `,n.appendChild(t),document.getElementById("columnToggleMenu").addEventListener("change",function(e){var t;e.target.classList.contains("toggle-vis")&&(t=parseInt(e.target.dataset.column,10),o.column(t).visible(e.target.checked))}))}});