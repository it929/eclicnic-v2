const eventBox = document.getElementById("event-box")
const countdownBox = document.getElementById("counter-box")
// console.log(eventBox.textContent)
// convert event date to miliseconds
const eventDate = Date.parse(eventBox.textContent) - 25320000
console.log(eventDate)
// get the current time stamp in miliseconds
// const curTimeStamp = new Date().getTime()
// console.log(curTimeStamp)
// get the interval between the date set and current time
const counDownTime = setInterval(()=>{
    const curTimeStamp = new Date().getTime()
    const timeInterval = eventDate - curTimeStamp
    const day = eventDate / (1000 * 60 * 60 * 24) - curTimeStamp / (1000 * 60 * 60 * 24)
    const getDay = Math.floor(day)
    const getHour = Math.floor((eventDate / (1000 * 60 * 60) - (curTimeStamp / (1000 * 60 * 60))) % 24)
    const getMinute = Math.floor((eventDate / (1000 * 60) - (curTimeStamp / (1000 * 60))) % 60)
    const getSeconds = Math.floor((eventDate / (1000) - (curTimeStamp / (1000))) % 60)
    if(timeInterval > 0){
        countdownBox.innerHTML = getDay +" days, " + getHour+" hours, "+ getMinute+ " minuites, "+ getSeconds + " seconds remaining"
    }
    else{
        clearInterval(counDownTime)
        countdownBox.innerHTML = "Time elapsed"
    }
}, 1000)
